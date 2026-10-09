"""
Scheduler service orchestrating schedules, tasks, catch-up evaluations, and logging.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4

from .config import SchedulerConfig
from .executor import TaskExecutor
from .history import SchedulerHistory
from .logger import CentralLogger, TaskLogger
from .models import ExecutionResult
from .notifier import Notifier
from .run_requests import RunRequestQueue
from .storage import StorageManager
from .timing import calculate_next_run, evaluate_schedule_trigger
from . import windows_task


class SchedulerService:
    """Core scheduler orchestrator coordinating persistence, execution, and logs."""

    def __init__(self, storage: Optional[StorageManager] = None) -> None:
        self.storage = storage or StorageManager()
        self.config = self.storage.get_config()

        # Initialize paths
        base_dir = self.storage.module_dir
        sys_log_path = base_dir / self.config.system_log_relative_path
        tasks_log_dir = base_dir / self.config.tasks_log_relative_path

        self.task_logger = TaskLogger(tasks_log_dir, default_retention=self.config.log_retention_runs)
        self.task_logger.task_ids.update({task.name: task.task_id for task in self.storage.list_tasks()})
        self.history = SchedulerHistory(self.storage, self.task_logger, self.config.output_retention_days)
        self.central_logger = CentralLogger(sys_log_path, history_store=self.history.store)
        self.executor = TaskExecutor(self.config)
        self.notifier = Notifier(self.config)
        self.run_request_queue = RunRequestQueue(base_dir)
        self._admin_worker_mode = False
        self._delegate_admin_tasks = False

    def refresh_config(self) -> SchedulerConfig:
        """Reload configuration from disk and update subcomponents."""
        self.config = self.storage.get_config()
        self.executor.update_config(self.config)
        self.notifier.update_config(self.config)
        self.task_logger.default_retention = self.config.log_retention_runs
        self.history.output_retention_days = self.config.output_retention_days
        return self.config

    # ── Task Execution ──

    def execute_task(
        self, task_name: str, dry_run: bool = False, *, visible_window: bool = False,
        origin: str = "manual", scheduled_for: Optional[str] = None, parent_id: Optional[str] = None,
    ) -> ExecutionResult:
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

        if self._admin_worker_mode:
            raise RuntimeError("The elevated worker can only execute queued Admin task requests.")

        # 1. Log start
        self.central_logger.log_task_start(task.name, task.environment, task.admin)

        # The regular daemon stays at limited privilege and delegates only Admin tasks.
        if self._delegate_admin_tasks and task.admin:
            result = self._execute_via_admin_worker(task, visible_window=visible_window)
        else:
            result = self.executor.execute(task, visible_window=visible_window)

        self._record_task_result(task, result, origin=origin, scheduled_for=scheduled_for, parent_id=parent_id)
        return result

    def _record_task_result(
        self, task, result: ExecutionResult, *, origin: str = "manual",
        scheduled_for: Optional[str] = None, parent_id: Optional[str] = None,
    ) -> None:
        """Persist task metadata and logs from the limited-privilege daemon only."""

        # 3. Update task metadata
        task.last_run_time = result.timestamp
        task.last_status = "success" if result.success else "failure"
        task.last_exit_code = result.exit_code
        task.last_duration_sec = result.duration_sec
        task.updated_at = datetime.now().isoformat()
        self.storage.save_task(task)

        # 4. Save task run log
        self.task_logger.log_run(
            result, script_code=task.code, retention=self.config.log_retention_runs, task_id=task.task_id
        )
        self.history.record_task(task, result, origin=origin, scheduled_for=scheduled_for, parent_id=parent_id)

        # 5. Log completion to central log
        if result.success:
            self.central_logger.log_task_completion(task.name, result.exit_code, result.duration_sec)
        else:
            err_snippet = result.error_message or result.stderr or f"Exit code {result.exit_code}"
            self.central_logger.log_task_failure(task.name, result.exit_code, err_snippet[:200])

        # 6. Notify
        self.notifier.notify_task_result(result)


    def _execute_via_admin_worker(self, task, *, visible_window: bool = False) -> ExecutionResult:
        status = windows_task.get_runner_status()
        worker = status.get("adminWorker", {})
        if not worker.get("installed"):
            message = "The elevated scheduler worker is not running. Re-run `scheduler setup windows` and start the runner."
            return ExecutionResult(
                task_name=task.name, schedule_name=task.schedule_name, timestamp=datetime.now().isoformat(),
                exit_code=1, stdout="", stderr=message, duration_sec=0.0, environment=task.environment,
                admin=task.admin, success=False, error_message=message,
            )
        # At logon both scheduled tasks start together; give the worker time to reach Running.
        for _ in range(30):
            if str(worker.get("state", "")).lower() == "running":
                break
            time.sleep(1)
            worker = windows_task.get_runner_status().get("adminWorker", {})
        if str(worker.get("state", "")).lower() != "running":
            message = "The elevated scheduler worker did not start. Restart it from Configuration & Shell Paths."
            return ExecutionResult(
                task_name=task.name, schedule_name=task.schedule_name, timestamp=datetime.now().isoformat(),
                exit_code=1, stdout="", stderr=message, duration_sec=0.0, environment=task.environment,
                admin=task.admin, success=False, error_message=message,
            )
        request = self.run_request_queue.enqueue(
            task.name,
            delay_seconds=10 if visible_window else 0,
            visible_window=visible_window,
            expires_after=timedelta(minutes=5) if visible_window else timedelta(hours=24),
        )
        while datetime.now() < request.expires_at:
            result_data = self.run_request_queue.read_result(request.request_id)
            if result_data is not None:
                self.run_request_queue.remove_result(request.request_id)
                result_data.pop("_visible_window", None)
                return ExecutionResult.from_dict(result_data)
            time.sleep(0.25)
        message = f"The elevated worker did not complete task '{task.name}' before the request expired."
        return ExecutionResult(
            task_name=task.name, schedule_name=task.schedule_name, timestamp=datetime.now().isoformat(),
            exit_code=1, stdout="", stderr=message, duration_sec=0.0, environment=task.environment,
            admin=task.admin, success=False, error_message=message,
        )

    def queue_runner_test(self, task_name: str, delay_seconds: int = 10) -> str:
        """Queue an admin task for delayed execution by the active Windows runner."""
        task = self.storage.get_task(task_name)
        if task is None:
            raise ValueError(f"Task '{task_name}' does not exist.")
        if not task.enabled:
            raise ValueError(f"Task '{task_name}' is disabled and cannot be used for a runner test.")
        if not task.admin:
            raise ValueError("The delayed elevated runner test is available only for tasks marked Admin.")

        status = windows_task.get_runner_status()
        if not status.get("installed"):
            raise RuntimeError("The Windows scheduler runner is not installed. Run `scheduler setup windows` first.")
        worker = status.get("adminWorker", {})
        if str(status.get("state", "")).lower() != "running" or str(worker.get("state", "")).lower() != "running":
            raise RuntimeError(
                "The Windows scheduler runner is not running. Start it from Configuration & Executables first; "
                "starting it may also run overdue catch-up tasks."
            )

        request = self.run_request_queue.enqueue(task_name, delay_seconds, visible_window=True)
        self.central_logger.log_system_info(
            f"Queued delayed runner test for task '{task_name}' (request {request.request_id}, run at {request.run_at.isoformat()})"
        )
        return request.run_at.strftime("%H:%M:%S")

    # ── Schedule Execution ──

    def execute_schedule(
        self, schedule_name: str, dry_run: bool = False, is_catchup: bool = False,
        scheduled_for: Optional[str] = None,
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
        started_at = datetime.now().astimezone().isoformat()
        schedule_run_id = uuid4().hex
        origin = "catch_up" if is_catchup else ("scheduled" if scheduled_for else "manual_schedule")
        for task in attached_tasks:
            res = self.execute_task(
                task.name, dry_run=dry_run, origin=origin, scheduled_for=scheduled_for,
                parent_id=schedule_run_id,
            )
            results.append(res)

        now = datetime.now()
        if not dry_run:
            self.history.record_schedule(
                schedule, started_at=started_at, finished_at=now.astimezone().isoformat(),
                results=results, origin=origin, scheduled_for=scheduled_for, record_id=schedule_run_id,
            )
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
                try:
                    ref = datetime.fromisoformat(sched.last_run_time or sched.created_at)
                except (TypeError, ValueError):
                    ref = now - timedelta(days=1)
                expected = calculate_next_run(sched.timing, after=ref)
                if sched.next_run_time and not is_catchup:
                    try:
                        expected = datetime.fromisoformat(sched.next_run_time)
                    except (TypeError, ValueError):
                        pass
                res_list = self.execute_schedule(
                    sched.name, dry_run=dry_run, is_catchup=is_catchup, scheduled_for=expected.isoformat()
                )
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
        startup_time = time.monotonic()
        last_schedule_check = startup_time - max(0.1, interval_sec)
        last_request_check = startup_time - 1.0
        self._delegate_admin_tasks = True
        try:
            while True:
                now = time.monotonic()
                if now - last_schedule_check >= max(0.1, interval_sec):
                    self.run_once(dry_run=dry_run)
                    ticks += 1
                    last_schedule_check = time.monotonic()
                if not dry_run and now - last_request_check >= 1.0:
                    self.process_runner_test_results()
                    last_request_check = time.monotonic()
                if max_ticks is not None and ticks >= max_ticks:
                    break
                until_schedule_check = max(0.0, max(0.1, interval_sec) - (time.monotonic() - last_schedule_check))
                until_request_check = max(0.0, 1.0 - (time.monotonic() - last_request_check)) if not dry_run else until_schedule_check
                time.sleep(min(until_schedule_check, until_request_check))
        except KeyboardInterrupt:
            self.central_logger.log_system_info("Scheduler daemon stopped by user (SIGINT)")
        except Exception as e:
            self.central_logger.log_error(f"Scheduler daemon halted unexpectedly: {e}")
            raise

    def run_admin_worker(self, interval_sec: float = 1.0, max_ticks: Optional[int] = None) -> None:
        """Run the highest-privilege worker, which executes only Admin requests."""
        self._admin_worker_mode = True
        ticks = 0
        try:
            while True:
                self.process_admin_requests()
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    return
                time.sleep(max(0.1, interval_sec))
        except KeyboardInterrupt:
            return

    def process_admin_requests(self) -> None:
        """Execute queued Admin tasks and publish results without writing scheduler state."""
        for request in self.run_request_queue.claim_due():
            try:
                task = self.storage.get_task(request.task_name)
                if task is None or not task.enabled or not task.admin:
                    reason = f"Task '{request.task_name}' is missing, disabled, or no longer marked Admin."
                    result = ExecutionResult(
                        task_name=request.task_name, schedule_name=None, timestamp=datetime.now().isoformat(),
                        exit_code=1, stdout="", stderr=reason, duration_sec=0.0, environment="", admin=True,
                        success=False, error_message=reason,
                    )
                else:
                    result = self.executor.execute(task, visible_window=request.visible_window)
                self.run_request_queue.write_result(request, result.to_dict())
            except Exception as exc:
                self.central_logger.log_error(f"Admin worker request {request.request_id} failed: {exc}")
                failure = ExecutionResult(
                    task_name=request.task_name, schedule_name=None, timestamp=datetime.now().isoformat(),
                    exit_code=1, stdout="", stderr=str(exc), duration_sec=0.0, environment="", admin=True,
                    success=False, error_message=str(exc),
                )
                try:
                    self.run_request_queue.write_result(request, failure.to_dict())
                except OSError:
                    pass
            finally:
                self.run_request_queue.complete(request)

    def process_runner_test_results(self) -> None:
        """Record detached visible-window test results in scheduler logs and metadata."""
        for result_path in sorted(self.run_request_queue.directory.glob("*.result.json")):
            request_id = result_path.name.removesuffix(".result.json")
            result_data = self.run_request_queue.read_result(request_id)
            if result_data is None:
                continue
            if not result_data.pop("_visible_window", False):
                continue
            task = self.storage.get_task(str(result_data.get("task_name", "")))
            if task is not None:
                result_data.pop("_visible_window", None)
                self._record_task_result(task, ExecutionResult.from_dict(result_data), origin="runner_test")
            self.run_request_queue.remove_result(request_id)
