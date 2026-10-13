"""Scheduler-specific recording and safe import of retained legacy logs."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from script_logging import EventRecord, HistoryStore, RunRecord

from .logger import TaskLogger, sanitize_filename
from .models import ExecutionResult, Schedule, Task
from .storage import StorageManager


class SchedulerHistory:
    """Adapt generic run history to scheduler entities and execution context."""

    _monitor_log_lock = threading.Lock()

    def __init__(self, storage: StorageManager, task_logger: TaskLogger, output_retention_days: int = 365) -> None:
        self.storage = storage
        self.task_logger = task_logger
        self.store = HistoryStore(storage.module_dir / "scheduler_history.sqlite3")
        self.output_retention_days = output_retention_days
        self._unmatched_legacy: List[Path] = []
        self.import_legacy_logs()
        coverage = self.store.list_events(source="scheduler", event_type="HISTORY_STARTED")
        if coverage:
            self.coverage_start = coverage[0].occurred_at
        else:
            self.coverage_start = datetime.now().astimezone().isoformat()
            self.store.append_event(
                EventRecord(
                    source="scheduler", event_type="HISTORY_STARTED", occurred_at=self.coverage_start,
                    message="Structured scheduler history capture started.", entity_type="history",
                )
            )

    @staticmethod
    def _aware(value: str) -> datetime:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone()

    def record_task(
        self, task: Task, result: ExecutionResult, *, origin: str,
        scheduled_for: Optional[str] = None, parent_id: Optional[str] = None,
    ) -> RunRecord:
        start = self._aware(result.timestamp)
        finish = start + timedelta(seconds=max(0.0, result.duration_sec))
        run = RunRecord(
            source="scheduler", entity_type="task", entity_id=task.task_id,
            display_name=task.name, started_at=start.isoformat(), finished_at=finish.isoformat(),
            status="success" if result.success else "failure", duration_sec=result.duration_sec,
            exit_code=result.exit_code, origin=origin, scheduled_for=scheduled_for,
            parent_id=parent_id, stdout=result.stdout, stderr=result.stderr,
            metadata={
                "schedule_name": task.schedule_name, "environment": result.environment,
                "admin": result.admin, "error_message": result.error_message,
            },
        )
        self.store.append_run(run)
        self.prune_output()
        return run

    def record_schedule(
        self, schedule: Schedule, *, started_at: str, finished_at: str,
        results: List[ExecutionResult], origin: str, scheduled_for: Optional[str],
        record_id: str,
    ) -> RunRecord:
        start = self._aware(started_at)
        finish = self._aware(finished_at)
        failed = sum(not result.success for result in results)
        run = RunRecord(
            record_id=record_id, source="scheduler", entity_type="schedule",
            entity_id=schedule.schedule_id, display_name=schedule.name,
            started_at=start.isoformat(), finished_at=finish.isoformat(),
            status="failure" if failed else "success", duration_sec=max(0.0, (finish - start).total_seconds()),
            exit_code=1 if failed else 0, origin=origin, scheduled_for=scheduled_for,
            stdout="", stderr="", metadata={"task_count": len(results), "failed_tasks": failed},
        )
        self.store.append_run(run)
        return run

    def monitor_log_path(self, rule: Any) -> Path:
        """Return the stable, per-rule event log path."""
        directory = self.task_logger.base_dir.parent / "monitored_processes"
        return directory / f"monitor-{sanitize_filename(rule.name)}-{rule.rule_id[:8]}.log"

    def record_monitor_event(
        self, rule: Any, event_type: str, message: str, *, level: str = "INFO",
        metadata: Optional[Dict[str, Any]] = None, occurred_at: Optional[str] = None,
    ) -> None:
        timestamp = self._aware(occurred_at or datetime.now().astimezone().isoformat()).isoformat()
        event = EventRecord(
            source="scheduler", entity_type="monitored_process", entity_id=rule.rule_id,
            event_type=event_type, occurred_at=timestamp, message=message, level=level,
            metadata=metadata or {},
        )
        self.store.append_event(event)
        log_path = self.monitor_log_path(rule)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        details = json.dumps(event.metadata, ensure_ascii=False, sort_keys=True)
        line = f"[{timestamp}] [{event_type}] {message}"
        if details != "{}":
            line += f" | {details}"
        with self._monitor_log_lock, log_path.open("a", encoding="utf-8") as stream:
            stream.write(line.replace("\r", " ").replace("\n", " ") + "\n")

    def record_monitor_action(
        self, rule: Any, action: str, *, origin: str, success: bool,
        started_at: str, duration_sec: float, message: str, metadata: Optional[Dict[str, Any]] = None,
    ) -> RunRecord:
        start = self._aware(started_at)
        finish = datetime.now().astimezone()
        status = "success" if success else "failure"
        details = {"action": action, **(metadata or {})}
        run = RunRecord(
            source="scheduler", entity_type="monitored_process", entity_id=rule.rule_id,
            display_name=rule.name, started_at=start.isoformat(), finished_at=finish.isoformat(),
            status=status, duration_sec=max(0.0, duration_sec), exit_code=0 if success else 1,
            origin=origin, stdout=message if success else "", stderr="" if success else message,
            metadata=details,
        )
        self.store.append_run(run)
        event_type = f"MONITOR_{action.upper()}_{'SUCCEEDED' if success else 'FAILED'}"
        self.record_monitor_event(
            rule, event_type, message, level="INFO" if success else "ERROR",
            metadata={"origin": origin, **details}, occurred_at=finish.isoformat(),
        )
        return run

    def list_monitor_runs(self, rule: Any) -> List[RunRecord]:
        return self.store.list_runs(
            source="scheduler", entity_type="monitored_process", entity_id=rule.rule_id,
        )

    def read_monitor_log(self, rule: Any, count: int = 500) -> List[str]:
        path = self.monitor_log_path(rule)
        if not path.exists():
            return []
        with self._monitor_log_lock, path.open("r", encoding="utf-8", errors="replace") as stream:
            lines = [line.rstrip("\r\n") for line in stream if line.strip()]
        return lines[-max(1, count):]

    def monitor_summary(self, rule: Any) -> Dict[str, Any]:
        runs = self.list_monitor_runs(rule)
        events = self.store.list_events(
            source="scheduler", entity_type="monitored_process", entity_id=rule.rule_id,
        )

        def summarize(days: Optional[int]) -> Dict[str, int]:
            cutoff = datetime.now().astimezone() - timedelta(days=days) if days is not None else None
            selected = [
                run for run in runs
                if cutoff is None or self._aware(run.started_at) >= cutoff
            ]
            return {
                "actions": len(selected),
                "starts": sum(run.metadata.get("action") == "start" for run in selected),
                "stops": sum(run.metadata.get("action") == "stop" for run in selected),
                "failures": sum(run.status != "success" for run in selected),
            }

        last = events[0] if events else None
        return {
            "last_7_days": summarize(7),
            "last_30_days": summarize(30),
            "last_365_days": summarize(365),
            "lifetime": summarize(None),
            "probe_error_incidents": sum(event.event_type == "MONITOR_PROBE_FAILED" for event in events),
            "last_event": ({
                "event_type": last.event_type, "occurred_at": last.occurred_at,
                "message": last.message,
            } if last else None),
            "log_file": str(self.monitor_log_path(rule)),
        }

    def clear_monitor_logs(self) -> None:
        directory = self.task_logger.base_dir.parent / "monitored_processes"
        if directory.exists():
            with self._monitor_log_lock:
                for path in directory.glob("monitor-*.log"):
                    path.write_text("", encoding="utf-8")

    def prune_output(self) -> None:
        cutoff = datetime.now().astimezone() - timedelta(days=max(1, self.output_retention_days))
        self.store.prune_output(cutoff.isoformat(), source="scheduler")

    def list_task_runs(self, task: Task) -> List[RunRecord]:
        return self.store.list_runs(source="scheduler", entity_type="task", entity_id=task.task_id)

    def list_schedule_runs(self, schedule: Schedule) -> List[RunRecord]:
        return self.store.list_runs(source="scheduler", entity_type="schedule", entity_id=schedule.schedule_id)

    def unmatched_legacy_logs(self) -> List[Path]:
        return list(self._unmatched_legacy)

    def clear(self) -> None:
        self.store.clear(source="scheduler")
        self.clear_monitor_logs()
        self.reset_coverage()

    def reset_coverage(self) -> None:
        """Start a fresh expected-run window after deleting run facts."""
        self.coverage_start = datetime.now().astimezone().isoformat()
        self.store.append_event(EventRecord(
            source="scheduler", event_type="HISTORY_STARTED", occurred_at=self.coverage_start,
            message="Structured scheduler history capture restarted after clearing history.",
            entity_type="history",
        ))

    def import_legacy_logs(self) -> None:
        """Backfill only logs with one unambiguous current task owner."""
        owners: dict[str, List[Task]] = {}
        for task in self.storage.list_tasks():
            owners.setdefault(sanitize_filename(task.name).casefold(), []).append(task)
        unmatched: List[Path] = []
        for path in sorted(self.task_logger.base_dir.glob("*.log")):
            if path.stem.startswith("task-"):
                continue
            candidates = owners.get(path.stem.casefold(), [])
            if len(candidates) != 1:
                unmatched.append(path)
                continue
            task = candidates[0]
            try:
                blocks = self.task_logger._split_runs(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                unmatched.append(path)
                continue
            for block in blocks:
                run = self._parse_legacy_block(task, path, block)
                if run is not None:
                    self.store.append_run(run)
        self._unmatched_legacy = unmatched

    @staticmethod
    def _parse_legacy_block(task: Task, path: Path, block: str) -> Optional[RunRecord]:
        def field(label: str) -> Optional[str]:
            match = re.search(rf"^{re.escape(label)}:\s*(.*)$", block, flags=re.MULTILINE)
            return match.group(1).strip() if match else None

        timestamp = field("Timestamp")
        exit_text = field("Exit Code")
        duration_text = field("Duration")
        if not timestamp or exit_text is None or duration_text is None:
            return None
        try:
            start = datetime.fromisoformat(timestamp).astimezone()
            exit_code = int(exit_text)
            duration = float(duration_text.split()[0])
        except (ValueError, IndexError):
            return None
        stdout_match = re.search(r"--- STANDARD OUTPUT ---\n(.*?)\n--- STANDARD ERROR ---", block, re.DOTALL)
        stderr_match = re.search(r"--- STANDARD ERROR ---\n(.*?)\n=== \[RUN END\]", block, re.DOTALL)
        stdout = stdout_match.group(1).strip() if stdout_match else ""
        stderr = stderr_match.group(1).strip() if stderr_match else ""
        record_id = hashlib.sha256((str(path) + "\n" + block).encode("utf-8")).hexdigest()
        return RunRecord(
            record_id=record_id, source="scheduler", entity_type="task", entity_id=task.task_id,
            display_name=task.name, started_at=start.isoformat(),
            finished_at=(start + timedelta(seconds=max(0.0, duration))).isoformat(),
            status="success" if exit_code == 0 else "failure", duration_sec=duration, exit_code=exit_code,
            origin="legacy", stdout=stdout, stderr=stderr,
            metadata={"legacy": True, "retained_only": True, "schedule_name": field("Schedule")},
        )
