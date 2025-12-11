#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manager: polls a filesystem-backed queue for jobs and spawns workers.

- Queue dir: ~/.dlmanager/queue
- Logs dir:  ~/.dlmanager/logs
- State dir: ~/.dlmanager/state
- PID file:  ~/.dlmanager/manager.pid

Each job results in launching a worker process:
    python -m dlmanager.workers.<method>_worker --job <path-to-job.json>

Workers stream JSON progress lines. The manager ingests those events, keeps
per-job state, and feeds a renderer (plain console or termdash dashboard).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .utils import (
    RUNTIME_DIR,
    LOGS_DIR,
    STATE_DIR,
    QUEUE_DIR,
    PID_FILE,
    ensure_runtime_dirs,
    which_or_none,
    method_order_by_preference,
)

try:  # Optional UI dependency
    from termdash import Line, Stat, TermDash

    TERMDASH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    TERMDASH_AVAILABLE = False
    Line = Stat = TermDash = None  # type: ignore

DEFAULT_POLL_INTERVAL = 1.0
PROGRESS_BAR_WIDTH = 18
STATUS_COLORS = {
    "running": "32",
    "completed": "32",
    "queued": "36",
    "starting": "33",
    "failed": "31",
    "error": "31",
}


@dataclass
class Job:
    id: str
    path: Path
    spec: dict
    status: str = "queued"
    worker_pid: Optional[int] = None
    method_used: Optional[str] = None
    last_update: float = field(default_factory=time.time)
    stats: dict = field(default_factory=dict)


class Manager:
    def __init__(
        self,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        *,
        ui_mode: str = "auto",
        verbosity: str = "stats",
    ):
        self.poll_interval = float(poll_interval)
        ensure_runtime_dirs()
        self.jobs: Dict[str, Job] = {}
        self._stop_event = threading.Event()
        self._reader_threads: List[threading.Thread] = []
        self._render_lock = threading.Lock()
        self.renderer = _build_renderer(ui_mode, verbosity)

        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def run_forever(self) -> None:
        self.renderer.start()
        self.renderer.notify("[INFO] dlmanager: manager running. Press Ctrl-C to stop.")
        try:
            while not self._stop_event.is_set():
                self._scan_queue()
                self._reap_finished()
                self._render()
                time.sleep(self.poll_interval)
        finally:
            self._cleanup()

    # --- Queue handling --------------------------------------------------
    def _scan_queue(self) -> None:
        for jf in sorted(QUEUE_DIR.glob("job_*.json")):
            try:
                spec = json.loads(jf.read_text(encoding="utf-8"))
                job_id = spec["id"]
            except Exception as exc:
                self.renderer.notify(f"[WARN] Bad job file {jf}: {exc}")
                continue
            if job_id in self.jobs:
                continue
            job = Job(id=job_id, path=jf, spec=spec, status="queued")
            self.jobs[job_id] = job
            self._launch_job(job)

    def _choose_method(self, job: Job) -> Optional[str]:
        desired = job.spec.get("method", "auto")
        if desired != "auto":
            return desired
        for meth in method_order_by_preference(job.spec):
            if which_or_none(meth):
                return meth
        return None

    def _launch_job(self, job: Job) -> None:
        method = self._choose_method(job)
        if not method:
            job.status = "error"
            job.stats = {"error": "No transfer method available (rsync/rclone/scp/native)."}
            self.renderer.notify(f"[ERROR] {job.id}: {job.stats['error']}")
            return

        job.method_used = method
        job.status = "starting"

        worker_mod = f"dlmanager.workers.{method}_worker"
        log_file = LOGS_DIR / f"{job.id}.{method}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_file.open("w", encoding="utf-8")
        cmd = [sys.executable, "-m", worker_mod, "--job", str(job.path)]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            bufsize=1,
        )
        job.worker_pid = proc.pid
        job.status = "running"
        job.stats.setdefault("method_hint", method)

        t = threading.Thread(target=self._read_worker, args=(job, proc), daemon=True)
        t.start()
        self._reader_threads.append(t)

    def _read_worker(self, job: Job, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Skip noisy lines
                self._merge_worker_event(job, data)
        finally:
            ret = proc.wait()
            if ret == 0 and job.status not in ("error", "failed"):
                job.status = "completed"
            elif job.status not in ("error", "failed"):
                job.status = "failed"
            job.last_update = time.time()

    def _merge_worker_event(self, job: Job, data: dict) -> None:
        stats = job.stats
        stats.update(data)
        if "bytes_dl" in data:
            stats["bytes_done"] = data["bytes_dl"]
        if "total_bytes" in data:
            stats["bytes_total"] = data["total_bytes"]
        if "speed_bps" in data:
            stats["bytes_per_s"] = data["speed_bps"]
        if "eta_s" in data:
            stats["eta_seconds"] = data["eta_s"]
        if "files_transferred" in data and "files_done" not in data:
            stats["files_done"] = data["files_transferred"]
        if "files_total" in data:
            stats["files_total"] = data["files_total"]
        if "current_file" in data:
            stats["current_file"] = data["current_file"]
        if job.method_used:
            stats.setdefault("method_hint", job.method_used)
        job.last_update = time.time()
        if "status" in data:
            job.status = data["status"]

    def _reap_finished(self) -> None:
        # Placeholder for future archival / cleanup work
        pass

    # --- Rendering -------------------------------------------------------
    def _render(self) -> None:
        with self._render_lock:
            self.renderer.render(self.jobs.values())

    def _cleanup(self) -> None:
        self.renderer.stop()
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt_bytes(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while v >= 1024 and idx < len(units) - 1:
        v /= 1024
        idx += 1
    return f"{v:.1f}{units[idx]}"


def _fmt_eta(seconds) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "--:--"
    mins, sec = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours:02d}:{mins:02d}:{sec:02d}"
    return f"{mins:02d}:{sec:02d}"


def _progress_summary(stats: dict) -> Tuple[Optional[float], str, str, str]:
    bytes_done = stats.get("bytes_done")
    bytes_total = stats.get("bytes_total")
    percent: Optional[float] = None
    if isinstance(bytes_done, (int, float)) and isinstance(bytes_total, (int, float)) and bytes_total > 0:
        percent = max(0.0, min(100.0, (bytes_done / bytes_total) * 100.0))
    elif stats.get("files_done") and stats.get("files_total"):
        try:
            percent = max(0.0, min(100.0, (stats["files_done"] / stats["files_total"]) * 100.0))
        except Exception:
            percent = None
    bar = _progress_bar(percent)
    percent_text = f"{percent:5.1f}%" if percent is not None else "  --.-%"
    speed_txt = f"{_fmt_bytes(stats.get('bytes_per_s'))}/s" if stats.get("bytes_per_s") else "-"
    eta_txt = _fmt_eta(stats.get("eta_seconds"))
    return percent, bar, percent_text, speed_txt, eta_txt


def _progress_bar(percent: Optional[float]) -> str:
    if percent is None:
        return " " * PROGRESS_BAR_WIDTH
    filled = int(PROGRESS_BAR_WIDTH * (percent / 100.0))
    filled = max(0, min(PROGRESS_BAR_WIDTH, filled))
    return "█" * filled + " " * (PROGRESS_BAR_WIDTH - filled)


def _status_color(status: str) -> str:
    return STATUS_COLORS.get(status.lower(), "")


def _build_renderer(ui_mode: str, verbosity: str):
    if ui_mode == "termdash" and not TERMDASH_AVAILABLE:
        print("[WARN] termdash requested but module unavailable; falling back to plain renderer.")
    if ui_mode == "termdash" and TERMDASH_AVAILABLE:
        return TermdashRenderer(verbosity=verbosity)
    if ui_mode == "auto" and TERMDASH_AVAILABLE:
        return TermdashRenderer(verbosity=verbosity)
    return PlainRenderer(verbosity=verbosity)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------
class BaseRenderer:
    def __init__(self, verbosity: str):
        self.verbosity = verbosity

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def notify(self, message: str) -> None:
        print(message)

    def render(self, jobs: Iterable[Job]) -> None:
        raise NotImplementedError


class PlainRenderer(BaseRenderer):
    def start(self) -> None:
        print("Plain dashboard ready.")

    def stop(self) -> None:
        print("\n[INFO] Manager stopped.")

    def render(self, jobs: Iterable[Job]) -> None:
        jobs = list(jobs)
        print("\033[2J\033[H", end="")
        print("dlmanager - active jobs\n")
        if not jobs:
            print("No jobs yet. Waiting for queue files in:", QUEUE_DIR)
            print("\n[Ctrl-C to stop]  Logs:", LOGS_DIR)
            return

        header = f"{'ID':8}  {'METHOD':8}  {'STATUS':10}  {'PROGRESS':>10}  {'SPEED':>12}  {'ETA':>8}  {'CUR.FILE'}"
        print(header)
        print("-" * len(header))

        for job in jobs:
            stats = job.stats
            _, _bar, percent_txt, speed_txt, eta_txt = _progress_summary(stats)
            file_name = stats.get("current_file") or "-"
            if len(file_name) > 42:
                file_name = "…" + file_name[-41:]
            method = job.method_used or stats.get("method_hint") or "-"
            print(
                f"{job.id[:8]:8}  {method:8}  {job.status:10}  "
                f"{percent_txt:>10}  {speed_txt:>12}  {eta_txt:>8}  {file_name}"
            )

        print("\n[Ctrl-C to stop]  Logs:", LOGS_DIR)


class TermdashRenderer(BaseRenderer):
    def __init__(self, verbosity: str):
        super().__init__(verbosity)
        self._dash: Optional[TermDash] = None
        self._job_lines: Dict[str, str] = {}

    def start(self) -> None:
        if not TERMDASH_AVAILABLE:
            raise RuntimeError("Termdash unavailable")
        self._dash = TermDash(
            align_columns=True,
            enable_separators=True,
            reserve_extra_rows=4,
            log_to_screen=False,
        ).start()
        header = Line(
            "header",
            [
                Stat("Job", "Job", no_expand=True, display_width=8),
                Stat("Method", "Method", no_expand=True, display_width=8),
                Stat("Status", "Status", no_expand=True, display_width=10),
                Stat("Bar", "Progress", no_expand=True, display_width=PROGRESS_BAR_WIDTH + 2),
                Stat("%", "%", no_expand=True, display_width=7),
                Stat("Speed", "Speed", no_expand=True, display_width=12),
                Stat("ETA", "ETA", no_expand=True, display_width=8),
                Stat("File", "File"),
            ],
            style="header",
        )
        self._dash.add_line("header", header)
        self._dash.add_separator()

    def stop(self) -> None:
        if self._dash:
            self._dash.stop()
            self._dash = None

    def notify(self, message: str) -> None:
        if self._dash:
            self._dash.log(message)
        else:
            super().notify(message)

    def render(self, jobs: Iterable[Job]) -> None:
        dash = self._dash
        if not dash:
            return
        for job in jobs:
            line_name = self._job_lines.get(job.id)
            if line_name is None:
                line_name = f"job_{len(self._job_lines) + 1}"
                self._job_lines[job.id] = line_name
                dash.add_line(
                    line_name,
                    Line(
                        line_name,
                        [
                            Stat("job", job.id[:8], no_expand=True, display_width=8),
                            Stat("method", job.method_used or "-", no_expand=True, display_width=8),
                            Stat(
                                "status",
                                job.status,
                                no_expand=True,
                                display_width=10,
                                color=lambda value, _=None: _status_color(str(value)),
                            ),
                            Stat("bar", " " * PROGRESS_BAR_WIDTH, format_string="[{}]", no_expand=True, display_width=PROGRESS_BAR_WIDTH + 2),
                            Stat("percent", "  --.-%", no_expand=True, display_width=7),
                            Stat("speed", "-", no_expand=True, display_width=12),
                            Stat("eta", "--:--", no_expand=True, display_width=8),
                            Stat("file", "-", format_string="{}"),
                        ],
                    ),
                )

            stats = job.stats
            _, bar, percent_txt, speed_txt, eta_txt = _progress_summary(stats)
            file_name = stats.get("current_file") or "-"
            if len(file_name) > 70:
                file_name = "…" + file_name[-69:]

            dash.update_stat(line_name, "job", job.id[:8])
            dash.update_stat(line_name, "method", job.method_used or stats.get("method_hint") or "-")
            dash.update_stat(line_name, "status", job.status)
            dash.update_stat(line_name, "bar", bar)
            dash.update_stat(line_name, "percent", percent_txt)
            dash.update_stat(line_name, "speed", speed_txt)
            dash.update_stat(line_name, "eta", eta_txt)
            dash.update_stat(line_name, "file", file_name)
