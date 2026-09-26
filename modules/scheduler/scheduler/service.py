"""
Scheduler service orchestrating schedules, tasks, catch-up evaluations, and logging.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional

from .config import SchedulerConfig
from .executor import TaskExecutor
from .logger import CentralLogger, TaskLogger
from .models import ExecutionResult
from .notifier import Notifier
from .storage import StorageManager
from .timing import calculate_next_run, evaluate_schedule_trigger


class SchedulerService:
    """Core scheduler orchestrator coordinating persistence, execution, and logs."""

    def __init__(self, storage: Optional[StorageManager] = None) -> None:
        self.storage = storage or StorageManager()
        self.config = self.storage.get_config()

        # Initialize paths
        base_dir = self.storage.module_dir
        sys_log_path = base_dir / self.config.system_log_relative_path
        tasks_log_dir = base_dir / self.config.tasks_log_relative_path

        self.central_logger = CentralLogger(sys_log_path)
        self.task_logger = TaskLogger(tasks_log_dir, default_retention=self.config.log_retention_runs)
        self.executor = TaskExecutor(self.config)
        self.notifier = Notifier(self.config)

    def refresh_config(self) -> SchedulerConfig:
        """Reload configuration from disk and update subcomponents."""
        self.config = self.storage.get_config()
        self.executor.update_config(self.config)
        self.notifier.update_config(self.config)
        self.task_logger.default_retention = self.config.log_retention_runs
        return self.config

    # ── Task Execution ──

    def execute_task(self, task_name: str, dry_run: bool = False) -> ExecutionResult:
        """Execute a single task by name."""
        task = self.storage.get_task(task_name)
        if not task:
            err_msg = f"Task '{task_name}' does not exist"
            self.central_logger.log_error(err_msg)
            return ExecutionResult(
                task_name=task_name,
                schedule_name=None,
                timestamp=datetime.now().isoformat(),
                exit_code=1,
                stdout="",
                stderr=err_msg,
                duration_sec=0.0,
                environment="",
                admin=False,
                success=False,
                error_message=err_msg,
            )

        if dry_run:
            msg = f"[DRY-RUN] Would execute task '{task.name}' in {task.environment} (admin={task.admin})"
            self.central_logger.log_system_info(msg)
            return ExecutionResult(
                task_name=task.name,
                schedule_name=task.schedule_name,
                timestamp=datetime.now().isoformat(),
                exit_code=0,
                stdout=msg,
                stderr="",
                duration_sec=0.0,
                environment=task.environment,
                admin=task.admin,
                success=True,
            )

        # 1. Log start
        self.central_logger.log_task_start(task.name, task.environment, task.admin)

        # 2. Execute script
        result = self.executor.execute(task)

        # 3. Update task metadata
        task.last_run_time = result.timestamp
        task.last_status = "success" if result.success else "failure"
        task.last_exit_code = result.exit_code
        task.last_duration_sec = result.duration_sec
        task.updated_at = datetime.now().isoformat()
        self.storage.save_task(task)

        # 4. Save task run log
        self.task_logger.log_run(result, script_code=task.code, retention=self.config.log_retention_runs)

        # 5. Log completion to central log
        if result.success:
            self.central_logger.log_task_completion(task.name, result.exit_code, result.duration_sec)
        else:
            err_snippet = result.error_message or result.stderr or f"Exit code {result.exit_code}"
            self.central_logger.log_task_failure(task.name, result.exit_code, err_snippet[:200])

        # 6. Notify
        self.notifier.notify_task_result(result)

        return result

    # ── Schedule Execution ──

    def execute_schedule(
        self, schedule_name: str, dry_run: bool = False, is_catchup: bool = False
    ) -> List[ExecutionResult]:
        """Execute all tasks attached to a schedule."""
        schedule = self.storage.get_schedule(schedule_name)
        if not schedule:
            err_msg = f"Schedule '{schedule_name}' does not exist"
            self.central_logger.log_error(err_msg)
            return []

        attached_tasks = [t for t in self.storage.get_attached_tasks(schedule_name) if t.enabled]
        self.central_logger.log_schedule_trigger(schedule.name, len(attached_tasks), is_catchup=is_catchup)
        self.notifier.notify_schedule_trigger(schedule.name, len(attached_tasks), is_catchup=is_catchup)

        results: List[ExecutionResult] = []
        for task in attached_tasks:
            res = self.execute_task(task.name, dry_run=dry_run)
            results.append(res)

        now = datetime.now()
        schedule.last_run_time = now.isoformat()
        schedule.next_run_time = calculate_next_run(schedule.timing, after=now).isoformat()
        schedule.updated_at = now.isoformat()
        self.storage.save_schedule(schedule)

        return results

    # ── Periodic Evaluation & Daemon Loop ──

    def run_once(self, dry_run: bool = False, now: Optional[datetime] = None) -> List[ExecutionResult]:
        """
        Evaluate all enabled schedules once.
        Triggers due runs or catch-up runs for missed schedules.
        """
        if now is None:
            now = datetime.now()

        all_results: List[ExecutionResult] = []
        schedules = self.storage.list_schedules()

        for sched in schedules:
            if not sched.enabled:
                continue

            should_trigger, is_catchup, reason = evaluate_schedule_trigger(sched, now=now)
            if should_trigger:
                if is_catchup:
                    self.central_logger.log_warning(f"Catch-up triggered for schedule '{sched.name}': {reason}")
                res_list = self.execute_schedule(sched.name, dry_run=dry_run, is_catchup=is_catchup)
                all_results.extend(res_list)
            else:
                # Update next_run_time if missing
                if not sched.next_run_time:
                    sched.next_run_time = calculate_next_run(sched.timing, after=now).isoformat()
                    self.storage.save_schedule(sched)

        return all_results

    def run_daemon(
        self, interval_sec: float = 10.0, dry_run: bool = False, max_ticks: Optional[int] = None
    ) -> None:
        """Run the scheduler daemon continuously."""
        self.central_logger.log_system_info(
            f"Scheduler daemon started (check interval: {interval_sec}s, dry_run={dry_run})"
        )
        ticks = 0
        try:
            while True:
                self.run_once(dry_run=dry_run)
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                time.sleep(interval_sec)
        except KeyboardInterrupt:
            self.central_logger.log_system_info("Scheduler daemon stopped by user (SIGINT)")
        except Exception as e:
            self.central_logger.log_error(f"Scheduler daemon halted unexpectedly: {e}")
            raise
