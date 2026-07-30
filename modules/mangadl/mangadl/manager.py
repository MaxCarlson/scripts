from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .concurrency import MAX_OUTER_WORKERS, Manga18FXConcurrencyPlan, plan_manga18fx_concurrency
from .models import JobState, WorkerSnapshot
from .state import StateStore
from .ui import ConsoleDashboard, DashboardRuntime, human_bytes, plain_identity

MANGA18FX_IMAGE_WORKERS_ENV = "MANGADL_MANGA18FX_IMAGE_WORKERS"
MAX_IMAGE_WORKERS = 8


@dataclass(slots=True)
class RunOptions:
    run_id: str
    destination: Path
    archive: Path
    state_db: Path
    log_dir: Path
    workers: int
    retries: int
    retry_wait: float
    gallery_config: Path | None = None
    cookies: Path | None = None
    cookies_browser: str | None = None
    rate: str | None = None
    hdporncomics_executable: str | None = None
    hdporncomics_threads: int = 8
    worker_start_delay: float = 2.0
    ui: bool = True


class DownloadManager:
    def __init__(self, options: RunOptions, store: StateStore) -> None:
        if options.worker_start_delay < 0:
            raise ValueError("worker_start_delay must be zero or greater")
        plan = plan_manga18fx_concurrency(options.workers, self._requested_image_workers())
        options.workers = plan.effective_workers
        self.options = options
        self.store = store
        self.target_workers = plan.effective_workers
        self.maximum_workers = plan.maximum_workers
        self.image_workers = plan.effective_image_workers
        self.logical_cpus = plan.logical_cpus
        self.concurrency_budget = plan.budget
        self.next_worker_start_at = 0.0
        self.events: queue.Queue[tuple[int, dict[str, Any] | None]] = queue.Queue()
        self.processes: dict[int, subprocess.Popen[str]] = {}
        self.assignments: dict[int, dict[str, Any]] = {}
        self.worker_costs: dict[int, int] = {}
        self.reader_done: set[int] = set()
        self.last_worker_status_log: dict[int, float] = {}
        self.snapshots = {slot: WorkerSnapshot(slot) for slot in range(1, self.target_workers + 1)}
        self.stop_requested = False
        self.runtime_notice = self._initial_concurrency_notice(plan)
        self.run_log = options.log_dir / options.run_id
        for folder in (self.run_log / "workers", self.run_log / "raw"):
            folder.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_log / "events.jsonl"
        self.logger = self._logger()
        self.dashboard = ConsoleDashboard(options.ui, options.run_id, self.run_log)
        if plan.adjusted:
            self.logger.warning(self.runtime_notice)

    @staticmethod
    def _requested_image_workers() -> int:
        raw = os.environ.get(MANGA18FX_IMAGE_WORKERS_ENV, "4")
        try:
            return max(1, int(raw))
        except ValueError:
            return 4

    @staticmethod
    def _initial_concurrency_notice(plan: Manga18FXConcurrencyPlan) -> str:
        if not plan.adjusted:
            return "Runtime concurrency is within the logical-CPU budget."
        return (
            "Adjusted requested concurrency "
            f"-w {plan.requested_workers} -I {plan.requested_image_workers} "
            f"({plan.requested_total}) to -w {plan.effective_workers} "
            f"-I {plan.effective_image_workers} ({plan.effective_total})."
        )

    def _logger(self) -> logging.Logger:
        logger = logging.getLogger(f"mangadl.{self.options.run_id}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        handler = logging.FileHandler(self.run_log / "manager.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        return logger

    def _active_slots(self) -> set[int]:
        return {slot for slot, process in self.processes.items() if process.poll() is None}

    def _future_aggregate(self, target_workers: int, image_workers: int) -> int:
        """Return the worst of current and steady-state aggregate concurrency."""
        total = 0
        active_slots = self._active_slots()
        highest_slot = max(active_slots | set(range(1, target_workers + 1)), default=0)
        for slot in range(1, highest_slot + 1):
            if slot in active_slots:
                active_cost = self.worker_costs.get(slot, 1)
                total += max(active_cost, image_workers) if slot <= target_workers else active_cost
            elif slot <= target_workers:
                total += image_workers
        return total

    def _set_runtime_notice(self, message: str) -> None:
        self.runtime_notice = message
        self.logger.info("runtime tuning: %s", message)

    def _adjust_runtime(self, action: str) -> None:
        if action == "workers_up":
            if self.target_workers >= self.maximum_workers:
                self._set_runtime_notice(
                    f"Worker target is already at the maximum of {self.maximum_workers}."
                )
                return
            candidate = self.target_workers + 1
            aggregate = self._future_aggregate(candidate, self.image_workers)
            if aggregate > self.concurrency_budget:
                self._set_runtime_notice(
                    f"Worker increase blocked: {aggregate} would exceed budget {self.concurrency_budget}."
                )
                return
            self.target_workers = candidate
            self.snapshots.setdefault(candidate, WorkerSnapshot(candidate))
            self._set_runtime_notice(
                f"Worker target increased to {candidate}; startup will be staggered by "
                f"{self.options.worker_start_delay:.1f}s."
            )
            return

        if action == "workers_down":
            if self.target_workers <= 1:
                self._set_runtime_notice("Worker target is already at the minimum of 1.")
                return
            self.target_workers -= 1
            self._set_runtime_notice(
                f"Worker target reduced to {self.target_workers}; excess active workers will drain."
            )
            return

        if action == "images_up":
            if self.image_workers >= MAX_IMAGE_WORKERS:
                self._set_runtime_notice(f"Image workers are already at the maximum of {MAX_IMAGE_WORKERS}.")
                return
            candidate = self.image_workers + 1
            aggregate = self._future_aggregate(self.target_workers, candidate)
            if aggregate > self.concurrency_budget:
                self._set_runtime_notice(
                    f"Image-worker increase blocked: {aggregate} would exceed budget {self.concurrency_budget}."
                )
                return
            self.image_workers = candidate
            self._set_runtime_notice(
                f"Image workers increased to {candidate}; applies to newly started Manga18FX jobs."
            )
            return

        if action == "images_down":
            if self.image_workers <= 1:
                self._set_runtime_notice("Image workers are already at the minimum of 1.")
                return
            self.image_workers -= 1
            self._set_runtime_notice(
                f"Image workers reduced to {self.image_workers}; applies to newly started Manga18FX jobs."
            )

    def _dashboard_runtime(self) -> DashboardRuntime:
        active_slots = self._active_slots()
        aggregate = sum(self.worker_costs.get(slot, 1) for slot in active_slots)
        return DashboardRuntime(
            active_workers=len(active_slots),
            target_workers=self.target_workers,
            image_workers=self.image_workers,
            aggregate=aggregate,
            budget=self.concurrency_budget,
            logical_cpus=self.logical_cpus,
            notice=self.runtime_notice,
        )

    def _visible_snapshots(self) -> dict[int, WorkerSnapshot]:
        slots = set(range(1, self.target_workers + 1)) | self._active_slots()
        return {slot: self.snapshots.setdefault(slot, WorkerSnapshot(slot)) for slot in sorted(slots)}

    def _worker_command(self, slot: int, job: dict[str, Any]) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "mangadl.worker",
            "--run-id",
            self.options.run_id,
            "--job-id",
            str(job["id"]),
            "--attempt-id",
            job["attempt_id"],
            "--worker",
            str(slot),
            "--url",
            job["canonical_url"],
            "--backend",
            job["backend"],
            "--destination",
            str(self.options.destination),
            "--archive",
            str(self.options.archive),
            "--partial-dir",
            str(self.options.destination / "_partial"),
            "--raw-log",
            str(self.run_log / "raw" / f"worker-{slot:02d}-gallery-dl.log"),
        ]
        if self.options.gallery_config:
            command.extend(["--gallery-config", str(self.options.gallery_config)])
        if self.options.cookies:
            command.extend(["--cookies", str(self.options.cookies)])
        if self.options.cookies_browser:
            command.extend(["--cookies-browser", self.options.cookies_browser])
        if self.options.rate:
            command.extend(["--rate", self.options.rate])
        if self.options.hdporncomics_executable:
            command.extend(["--hdporncomics-executable", self.options.hdporncomics_executable])
        command.extend(["--hdporncomics-threads", str(self.options.hdporncomics_threads)])
        return command

    def _start_worker(self, slot: int, job: dict[str, Any]) -> None:
        child_env = os.environ.copy()
        child_env[MANGA18FX_IMAGE_WORKERS_ENV] = str(self.image_workers)
        process = subprocess.Popen(
            self._worker_command(slot, job),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            env=child_env,
        )
        self.processes[slot] = process
        self.assignments[slot] = job
        self.worker_costs[slot] = self.image_workers if job["backend"] == "manga18fx" else 1
        self.next_worker_start_at = time.monotonic() + self.options.worker_start_delay
        snapshot = self.snapshots.setdefault(slot, WorkerSnapshot(slot))
        snapshot.state = "run"
        snapshot.url = job["canonical_url"]
        snapshot.backend = job["backend"]
        snapshot.attempt = job["attempts"]
        self.logger.info(
            "dispatch worker=%02d pid=%s job=%s attempt=%s image_workers=%s next_start_in=%.2fs url=%s",
            slot,
            process.pid,
            job["id"],
            job["attempt_id"],
            self.worker_costs[slot],
            self.options.worker_start_delay,
            job["canonical_url"],
        )
        self._write_worker_log(
            slot, "START", f"attempt={job['attempts']} {plain_identity(job['canonical_url'])}", elapsed=0.0
        )

        def read_events() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    self.logger.warning("worker=%02d malformed event: %s", slot, line.rstrip())
                    continue
                self.events.put((slot, event))
            self.events.put((slot, None))

        threading.Thread(target=read_events, daemon=True).start()

    def _write_worker_log(self, slot: int, status: str, message: str, *, elapsed: float) -> None:
        """Write ytaedl-compatible wall/elapsed/status worker activity records."""
        total_ms = max(0, int(elapsed * 1000))
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        elapsed_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
        wall = time.strftime("%H:%M:%S")
        path = self.run_log / "workers" / f"worker-{slot:02d}.log"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{wall}][{elapsed_text}] {status:<16} {message}\n")

    def _apply(self, slot: int, event: dict[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        if not self.store.apply_event(event):
            self.logger.warning("ignored stale event worker=%02d attempt=%s", slot, event.get("attempt_id"))
            return
        data = event.get("data", {})
        snapshot = self.snapshots.setdefault(slot, WorkerSnapshot(slot))
        snapshot.state = data.get("state", snapshot.state).replace("running", "run")
        for name in (
            "title",
            "site",
            "images_done",
            "images_total",
            "bytes_done",
            "bytes_total",
            "current_bps",
            "average_bps",
            "current_ips",
            "average_ips",
            "elapsed",
            "message",
            "backend",
        ):
            if name in data and data[name] is not None:
                setattr(snapshot, name, data[name])
        if event["event"] == "heartbeat":
            self.store.heartbeat(event["job_id"], event["attempt_id"])
            now = time.monotonic()
            if now - self.last_worker_status_log.get(slot, 0.0) >= 5.0:
                identity = plain_identity(event["url"], data.get("site", ""))
                images = f"{data.get('images_done', 0)}/{data.get('images_total') or '?'} img"
                rate = human_bytes(data.get("current_bps", 0), "/s")
                self._write_worker_log(
                    slot,
                    "DOWNLOADING",
                    f"{identity}  {images}  {human_bytes(data.get('bytes_done', 0))}  now={rate}",
                    elapsed=float(data.get("elapsed", 0.0)),
                )
                self.last_worker_status_log[slot] = now
        elif event["event"] == "job_complete":
            state = JobState._value2member_map_.get(data.get("state"), JobState.SUCCEEDED)
            self.store.complete(event["job_id"], event["attempt_id"], state)
            status = (
                "FINISH_SKIPPED"
                if state == JobState.SKIPPED_ARCHIVE
                else "FINISH_INCOMPLETE" if state == JobState.SUCCEEDED_INCOMPLETE else "FINISH_SUCCESS"
            )
            self._write_worker_log(
                slot,
                status,
                f"{plain_identity(event['url'], data.get('site', ''))}  {data.get('images_done', 0)} img  {human_bytes(data.get('bytes_done', 0))}",
                elapsed=float(data.get("elapsed", snapshot.elapsed)),
            )
        elif event["event"] in {"job_retryable_failure", "job_terminal_failure"}:
            job = next((row for row in self.store.jobs(self.options.run_id) if row["id"] == event["job_id"]), None)
            category = data.get("category", "backend")
            message = data.get("message", "backend failed")
            if event["event"] == "job_retryable_failure" and job and job["attempts"] <= self.options.retries:
                self.store.retry(
                    event["job_id"],
                    event["attempt_id"],
                    self.options.retry_wait * 2 ** (job["attempts"] - 1),
                    category,
                    message,
                )
                self._write_worker_log(
                    slot,
                    "FINISH_RETRY",
                    f"{plain_identity(event['url'])}  {category}: {message}",
                    elapsed=float(data.get("elapsed", snapshot.elapsed)),
                )
            else:
                state = JobState._value2member_map_.get(data.get("state"), JobState.FAILED_BACKEND)
                self.store.complete(event["job_id"], event["attempt_id"], state, category, message)
                self._write_worker_log(
                    slot,
                    "FINISH_FAILED",
                    f"{plain_identity(event['url'])}  {category}: {message}",
                    elapsed=float(data.get("elapsed", snapshot.elapsed)),
                )

    def _keyboard(self) -> None:
        if not self.options.ui or not sys.stdin.isatty():
            return
        if os.name == "nt":
            import msvcrt

            while msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in {"\x00", "\xe0"}:
                    key = {"H": "UP", "P": "DOWN"}.get(msvcrt.getwch(), "")
                action = self.dashboard.handle_key(key, max(self.snapshots, default=self.target_workers))
                if action:
                    self._adjust_runtime(action)

    def run(self) -> int:
        self.store.recover_expired(self.options.run_id)
        last_render = 0.0
        try:
            while True:
                self._keyboard()
                try:
                    while True:
                        slot, event = self.events.get_nowait()
                        if event is None:
                            self.reader_done.add(slot)
                        else:
                            self._apply(slot, event)
                except queue.Empty:
                    pass

                slots = sorted(set(range(1, self.target_workers + 1)) | set(self.processes))
                started_worker = False
                for slot in slots:
                    process = self.processes.get(slot)
                    if process is not None and process.poll() is None:
                        continue
                    if process is not None:
                        if slot not in self.reader_done:
                            continue
                        assignment = self.assignments.pop(slot)
                        job = next(
                            (row for row in self.store.jobs(self.options.run_id) if row["id"] == assignment["id"]), None
                        )
                        if job and job["state"] in {"leased", "running"}:
                            message = f"worker exited {process.returncode} without a terminal event"
                            self._write_worker_log(
                                slot,
                                "FINISH_FAILED",
                                f"{plain_identity(job['canonical_url'])}  {message}",
                                elapsed=self.snapshots[slot].elapsed,
                            )
                            if job["attempts"] <= self.options.retries:
                                self.store.retry(
                                    job["id"], job["attempt_id"], self.options.retry_wait, "backend", message
                                )
                            else:
                                self.store.complete(
                                    job["id"], job["attempt_id"], JobState.FAILED_BACKEND, "backend", message
                                )
                        self.processes.pop(slot, None)
                        self.worker_costs.pop(slot, None)
                        self.reader_done.discard(slot)
                        self.snapshots[slot] = WorkerSnapshot(slot)
                    if slot > self.target_workers:
                        continue
                    if self.stop_requested or self.dashboard.paused_all or slot in self.dashboard.paused_workers:
                        continue
                    if started_worker or time.monotonic() < self.next_worker_start_at:
                        continue
                    leased = self.store.lease(self.options.run_id, slot)
                    if leased is not None:
                        self._start_worker(slot, dict(leased))
                        started_worker = True

                counts = self.store.counts(self.options.run_id)
                active = any(process.poll() is None for process in self.processes.values())
                pending = (
                    counts.get("queued", 0)
                    + counts.get("retry_wait", 0)
                    + counts.get("leased", 0)
                    + counts.get("running", 0)
                )
                if (not active and pending == 0) or (self.stop_requested and not active):
                    break
                if time.monotonic() - last_render >= 0.25:
                    self.dashboard.render(counts, self._visible_snapshots(), self._dashboard_runtime())
                    last_render = time.monotonic()
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop_requested = True
            for process in self.processes.values():
                process.terminate()
            for process in self.processes.values():
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        counts = self.store.counts(self.options.run_id)
        failed = sum(value for key, value in counts.items() if key.startswith("failed_"))
        status = "failed" if failed else ("interrupted" if self.stop_requested else "succeeded")
        self.store.finish_run(self.options.run_id, status)
        summary = {
            "run_id": self.options.run_id,
            "status": status,
            "counts": counts,
            "jobs": self.store.jobs(self.options.run_id),
        }
        (self.run_log / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        if self.options.ui:
            print()
        print(json.dumps({"run_id": self.options.run_id, "status": status, "counts": counts}, sort_keys=True))
        return 1 if failed else 0
