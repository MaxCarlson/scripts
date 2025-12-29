"""
Task Queue Manager

Handles filesystem-based task queue operations for AI CLI coordination.
Provides atomic task state transitions and result tracking.
"""

import json
import os
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    QUEUED = "queued"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(int, Enum):
    """Task priority levels (1=lowest, 5=highest)."""
    LOWEST = 1
    LOW = 2
    NORMAL = 3
    HIGH = 4
    HIGHEST = 5


class TaskQueueError(Exception):
    """Base exception for task queue operations."""
    pass


class TaskNotFoundError(TaskQueueError):
    """Task file not found in expected location."""
    pass


class TaskStateError(TaskQueueError):
    """Invalid task state transition."""
    pass


class TaskQueue:
    """
    Filesystem-based task queue manager.

    Provides atomic operations for task lifecycle management:
    - Task creation and submission
    - State transitions (queued → assigned → in_progress → completed/failed)
    - Result tracking and retrieval
    """

    def __init__(self, queue_path: Optional[str] = None):
        """
        Initialize task queue manager.

        Args:
            queue_path: Root directory for task queue.
                       Defaults to TASK_QUEUE_PATH env var or ./task_queue
        """
        self.queue_path = Path(queue_path or os.getenv("TASK_QUEUE_PATH", "./task_queue"))
        self._ensure_directories()

    def _ensure_directories(self):
        """Create task queue directory structure if it doesn't exist."""
        for status in TaskStatus:
            (self.queue_path / status.value).mkdir(parents=True, exist_ok=True)
        (self.queue_path / "results").mkdir(parents=True, exist_ok=True)
        logger.info(f"Task queue initialized at {self.queue_path}")

    def _get_task_path(self, task_id: str, status: TaskStatus) -> Path:
        """Get full path to task file."""
        return self.queue_path / status.value / f"{task_id}.json"

    def _read_task(self, task_id: str, status: TaskStatus) -> Dict[str, Any]:
        """Read task data from file."""
        path = self._get_task_path(task_id, status)
        if not path.exists():
            raise TaskNotFoundError(f"Task {task_id} not found in {status.value}/")

        with open(path, 'r') as f:
            return json.load(f)

    def _write_task(self, task_id: str, status: TaskStatus, data: Dict[str, Any]):
        """Write task data to file."""
        path = self._get_task_path(task_id, status)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def create_task(
        self,
        project_id: str,
        task_title: str,
        description: str,
        task_id: Optional[str] = None,
        priority: int = TaskPriority.NORMAL,
        cli_preference: str = "claude",
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create and submit a new task to the queue.

        Args:
            project_id: UUID of the project this task belongs to
            task_title: Short title for the task
            description: Detailed task description/instructions
            task_id: Optional task UUID (generated if not provided)
            priority: Task priority (1-5, default 3)
            cli_preference: Preferred CLI tool (default "claude")
            context: Additional context (project_name, related_files, etc.)
            constraints: Task constraints (max_duration, timeout_action, etc.)

        Returns:
            Task UUID

        Example:
            >>> queue = TaskQueue()
            >>> task_id = queue.create_task(
            ...     project_id="550e8400-e29b-41d4-a716-446655440000",
            ...     task_title="Implement user authentication",
            ...     description="Add JWT-based authentication to the API",
            ...     priority=TaskPriority.HIGH
            ... )
        """
        task_id = task_id or str(uuid.uuid4())

        task_data = {
            "task_id": task_id,
            "project_id": project_id,
            "task_title": task_title,
            "description": description,
            "priority": priority,
            "cli_preference": cli_preference,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": "kmtui",
            "status": TaskStatus.QUEUED.value,
            "context": context or {
                "project_name": "",
                "related_files": [],
                "dependencies": [],
                "tags": []
            },
            "constraints": constraints or {
                "max_duration_seconds": 3600,
                "require_human_approval": False,
                "timeout_action": "fail"
            }
        }

        self._write_task(task_id, TaskStatus.QUEUED, task_data)
        logger.info(f"Task {task_id} created and queued: {task_title}")

        return task_id

    def move_task(
        self,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        updates: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Atomically move task between states with optional updates.

        Args:
            task_id: Task UUID
            from_status: Current task status
            to_status: Target task status
            updates: Optional dict of fields to update

        Returns:
            True if successful, False if task not found

        Raises:
            TaskStateError: If state transition is invalid

        Example:
            >>> queue.move_task(
            ...     task_id,
            ...     TaskStatus.QUEUED,
            ...     TaskStatus.ASSIGNED,
            ...     updates={"assigned_to": "claude-code"}
            ... )
        """
        source = self._get_task_path(task_id, from_status)

        if not source.exists():
            logger.warning(f"Task {task_id} not found in {from_status.value}/")
            return False

        # Read current task data
        try:
            task_data = self._read_task(task_id, from_status)
        except TaskNotFoundError:
            return False

        # Apply updates
        if updates:
            task_data.update(updates)

        # Update status
        task_data['status'] = to_status.value

        # Add timestamp for this transition
        timestamp_field = f"{to_status.value}_at"
        task_data[timestamp_field] = datetime.utcnow().isoformat() + "Z"

        # Write to destination (atomic via temp file)
        dest = self._get_task_path(task_id, to_status)
        temp_file = dest.with_suffix('.tmp')

        try:
            with open(temp_file, 'w') as f:
                json.dump(task_data, f, indent=2)

            # Atomic rename
            os.rename(temp_file, dest)

            # Remove original
            os.unlink(source)

            logger.info(f"Task {task_id} moved from {from_status.value} to {to_status.value}")
            return True

        except Exception as e:
            # Clean up temp file if it exists
            if temp_file.exists():
                temp_file.unlink()
            logger.error(f"Failed to move task {task_id}: {e}")
            raise

    def assign_task(
        self,
        task_id: str,
        assigned_to: str,
        worker_pid: Optional[int] = None
    ) -> bool:
        """
        Assign a queued task to a CLI worker.

        Args:
            task_id: Task UUID
            assigned_to: CLI identifier (e.g., "claude-code")
            worker_pid: Optional worker process ID

        Returns:
            True if successful
        """
        updates = {
            "assigned_to": assigned_to,
            "assigned_at": datetime.utcnow().isoformat() + "Z"
        }

        if worker_pid:
            updates["worker_pid"] = worker_pid

        return self.move_task(task_id, TaskStatus.QUEUED, TaskStatus.ASSIGNED, updates)

    def start_task(self, task_id: str, worker_pid: Optional[int] = None) -> bool:
        """
        Mark assigned task as in-progress.

        Args:
            task_id: Task UUID
            worker_pid: Optional worker process ID

        Returns:
            True if successful
        """
        updates = {"started_at": datetime.utcnow().isoformat() + "Z"}

        if worker_pid:
            updates["worker_pid"] = worker_pid

        return self.move_task(task_id, TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, updates)

    def complete_task(
        self,
        task_id: str,
        result: Dict[str, Any],
        output_path: Optional[str] = None
    ) -> bool:
        """
        Mark in-progress task as completed with results.

        Args:
            task_id: Task UUID
            result: Task result data (success, summary, changes, etc.)
            output_path: Optional path to results directory

        Returns:
            True if successful

        Example:
            >>> queue.complete_task(
            ...     task_id,
            ...     result={
            ...         "success": True,
            ...         "summary": "Implemented authentication",
            ...         "files_modified": 5
            ...     }
            ... )
        """
        updates = {
            "completed_at": datetime.utcnow().isoformat() + "Z",
            "result": result
        }

        if output_path:
            updates["output_path"] = output_path

        # Calculate duration
        try:
            task_data = self._read_task(task_id, TaskStatus.IN_PROGRESS)
            started_at = datetime.fromisoformat(task_data["started_at"].replace("Z", ""))
            completed_at = datetime.utcnow()
            duration = (completed_at - started_at).total_seconds()
            updates["duration_seconds"] = int(duration)
        except Exception as e:
            logger.warning(f"Could not calculate duration for task {task_id}: {e}")

        return self.move_task(task_id, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED, updates)

    def fail_task(
        self,
        task_id: str,
        error: Dict[str, Any],
        exit_code: int = 1,
        retry_count: int = 0,
        max_retries: int = 3
    ) -> bool:
        """
        Mark in-progress task as failed with error information.

        Args:
            task_id: Task UUID
            error: Error details (type, message, traceback, etc.)
            exit_code: Process exit code
            retry_count: Number of retries attempted
            max_retries: Maximum retries allowed

        Returns:
            True if successful

        Example:
            >>> queue.fail_task(
            ...     task_id,
            ...     error={
            ...         "type": "TimeoutError",
            ...         "message": "Task exceeded 3600 seconds"
            ...     },
            ...     retry_count=1,
            ...     max_retries=3
            ... )
        """
        updates = {
            "failed_at": datetime.utcnow().isoformat() + "Z",
            "exit_code": exit_code,
            "error": error,
            "retry_count": retry_count,
            "max_retries": max_retries
        }

        # Calculate duration
        try:
            task_data = self._read_task(task_id, TaskStatus.IN_PROGRESS)
            started_at = datetime.fromisoformat(task_data["started_at"].replace("Z", ""))
            failed_at = datetime.utcnow()
            duration = (failed_at - started_at).total_seconds()
            updates["duration_seconds"] = int(duration)
        except Exception as e:
            logger.warning(f"Could not calculate duration for task {task_id}: {e}")

        return self.move_task(task_id, TaskStatus.IN_PROGRESS, TaskStatus.FAILED, updates)

    def update_heartbeat(self, task_id: str) -> bool:
        """
        Update heartbeat timestamp for in-progress task.

        Args:
            task_id: Task UUID

        Returns:
            True if successful
        """
        try:
            task_data = self._read_task(task_id, TaskStatus.IN_PROGRESS)
            task_data["heartbeat_at"] = datetime.utcnow().isoformat() + "Z"
            self._write_task(task_id, TaskStatus.IN_PROGRESS, task_data)
            return True
        except TaskNotFoundError:
            logger.warning(f"Cannot update heartbeat: task {task_id} not in progress")
            return False

    def get_task(self, task_id: str, status: Optional[TaskStatus] = None) -> Optional[Dict[str, Any]]:
        """
        Get task data by ID, optionally searching specific status.

        Args:
            task_id: Task UUID
            status: Optional specific status to check

        Returns:
            Task data dict or None if not found
        """
        if status:
            try:
                return self._read_task(task_id, status)
            except TaskNotFoundError:
                return None

        # Search all statuses
        for status_enum in TaskStatus:
            try:
                return self._read_task(task_id, status_enum)
            except TaskNotFoundError:
                continue

        return None

    def list_tasks(self, status: TaskStatus, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        List all tasks in a given status.

        Args:
            status: Task status to query
            limit: Optional maximum number of tasks to return

        Returns:
            List of task data dicts (sorted by created_at)
        """
        status_dir = self.queue_path / status.value
        task_files = sorted(status_dir.glob("*.json"))

        if limit:
            task_files = task_files[:limit]

        tasks = []
        for task_file in task_files:
            try:
                with open(task_file, 'r') as f:
                    tasks.append(json.load(f))
            except Exception as e:
                logger.error(f"Error reading task file {task_file}: {e}")

        # Sort by priority (descending) then created_at (ascending)
        tasks.sort(key=lambda t: (-t.get("priority", 3), t.get("created_at", "")))

        return tasks

    def get_queue_stats(self) -> Dict[str, int]:
        """
        Get task counts for each status.

        Returns:
            Dict mapping status names to task counts

        Example:
            >>> stats = queue.get_queue_stats()
            >>> print(f"Queued: {stats['queued']}, In Progress: {stats['in_progress']}")
        """
        stats = {}
        for status in TaskStatus:
            status_dir = self.queue_path / status.value
            count = len(list(status_dir.glob("*.json")))
            stats[status.value] = count

        return stats

    def cleanup_stale_tasks(self, stale_threshold_seconds: int = 300) -> int:
        """
        Find and fail tasks with no heartbeat for > threshold.

        Args:
            stale_threshold_seconds: Seconds without heartbeat before marking stale

        Returns:
            Number of tasks failed
        """
        now = datetime.utcnow()
        stale_count = 0

        for task_file in (self.queue_path / TaskStatus.IN_PROGRESS.value).glob("*.json"):
            try:
                with open(task_file, 'r') as f:
                    task_data = json.load(f)

                last_heartbeat_str = task_data.get(
                    "heartbeat_at",
                    task_data.get("started_at", "")
                )

                if not last_heartbeat_str:
                    continue

                last_heartbeat = datetime.fromisoformat(last_heartbeat_str.replace("Z", ""))
                elapsed = (now - last_heartbeat).total_seconds()

                if elapsed > stale_threshold_seconds:
                    logger.warning(f"Task {task_data['task_id']} is stale (no heartbeat for {elapsed}s)")
                    self.fail_task(
                        task_data["task_id"],
                        error={
                            "type": "StalledTask",
                            "message": f"No heartbeat for {elapsed} seconds",
                            "recovery_action": "retry"
                        }
                    )
                    stale_count += 1

            except Exception as e:
                logger.error(f"Error checking task file {task_file}: {e}")

        return stale_count
