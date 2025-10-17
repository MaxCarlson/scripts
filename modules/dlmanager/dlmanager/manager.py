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

The worker prints JSON lines with progress updates to stdout.
Manager parses those lines and keeps an in-memory registry.
A simple live view is printed to the console and updated in place.

This file aims to remain portable across Windows, Linux, and Termux.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List

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

DEFAULT_POLL_INTERVAL = 1.0


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
    def __init__(self, poll_interval: float = DEFAULT_POLL_INTERVAL):
        self.poll_interval = float(poll_interval)
        ensure_runtime_dirs()
        self.jobs: Dict[str, Job] = {}
        self._stop_event = threading.Event()
        self._printer_lock = threading.Lock()
        self._reader_threads: List[threading.Thread] = []

        # Write PID
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def run_forever(self) -> None:
        print("[INFO] dlmanager: manager running. Press Ctrl-C to stop.")
        try:
            while not self._stop_event.is_set():
                self._scan_queue()
                self._reap_finished()
                self._render()
                time.sleep(self.poll_interval)
        finally:
            self._cleanup()

    # --- Queue & job handling -------------------------------------------------

    def _scan_queue(self) -> None:
        for jf in sorted(QUEUE_DIR.glob("job_*.json")):
            try:
                spec = json.loads(jf.read_text(encoding="utf-8"))
                job_id = spec["id"]
            except Exception as e:
                print(f"[WARN] Bad job file {jf}: {e}")
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
        # Auto selection based on availability
        for meth in method_order_by_preference():
            if which_or_none(meth):
                return meth
        return None

    def _launch_job(self, job: Job) -> None:
        method = self._choose_method(job)
        if not method:
            job.status = "error"
            job.stats = {"error": "No available transfer method found (need rsync, rclone, or scp)."}
            return

        job.method_used = method
        job.status = "starting"

        worker_mod = f"dlmanager.workers.{method}_worker"
        log_file = (LOGS_DIR / f"{job.id}.{method}.log")
        log_handle = log_file.open("w", encoding="utf-8")
        # Spawn worker as: python -m dlmanager.workers.rsync_worker --job <jsonfile>
        cmd = [sys.executable, "-m", worker_mod, "--job", str(job.path)]
        # NOTE: we keep stdout=PIPE for progress, stderr->log
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            bufsize=1,
        )
        job.worker_pid = proc.pid
        job.status = "running"

        # Reader thread to consume worker JSONL
        t = threading.Thread(target=self._read_worker, args=(job, proc), daemon=True)
        t.start()
        self._reader_threads.append(t)

    def _read_worker(self, job: Job, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # Non-JSON worker chatter; ignore but could append to per-job debug
                    continue
                job.stats.update(data)
                job.last_update = time.time()
                # The worker may emit status changes
                if "status" in data:
                    job.status = data["status"]
        finally:
            # Wait for completion & mark status
            ret = proc.wait()
            if ret == 0 and job.status not in ("error", "failed"):
                job.status = "completed"
            elif job.status not in ("error", "failed"):
                job.status = "failed"
            job.last_update = time.time()

    def _reap_finished(self) -> None:
        # Could perform cleanup or archival
        pass

    # --- Rendering ------------------------------------------------------------

    def _render(self) -> None:
        with self._printer_lock:
            # Clear screen-lite (portable)
            print("\033[2J\033[H", end="")
            print("dlmanager — active jobs\n")
            if not self.jobs:
                print("No jobs yet. Waiting for queue files in: ", QUEUE_DIR)
                return
            # Print a simple table
            rows = []
            for j in self.jobs.values():
                stats = j.stats
                row = {
                    "id": j.id[:8],
                    "method": j.method_used or "-",
                    "status": j.status,
                    "file": stats.get("current_file", "-"),
                    "done": _fmt_bytes(stats.get("bytes_done")),
                    "total": _fmt_bytes(stats.get("bytes_total")),
                    "speed": _fmt_bytes(stats.get("bytes_per_s")) + "/s" if stats.get("bytes_per_s") else "-",
                    "files": f"{stats.get('files_done','-')}/{stats.get('files_total','-')}",
                }
                rows.append(row)

            hdr = f"{'ID':8}  {'METHOD':8}  {'STATUS':10}  {'CUR.FILE':30}  {'DONE':>10}  {'TOTAL':>10}  {'SPEED':>12}  {'FILES':>9}"
            print(hdr)
            print("-" * len(hdr))
            for r in rows:
                cf = (r["file"] or "-")
                if len(cf) > 30:
                    cf = "…" + cf[-29:]
                print(
                    f"{r['id']:8}  {r['method']:8}  {r['status']:10}  {cf:30}  "
                    f"{r['done']:>10}  {r['total']:>10}  {r['speed']:>12}  {r['files']:>9}"
                )
            print("\n[Ctrl-C to stop]  Logs:", LOGS_DIR)

    def _cleanup(self) -> None:
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def _fmt_bytes(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.1f}{units[i]}"
