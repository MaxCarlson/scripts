"""
Orchestrator API Router
Endpoints for monitoring workers, tasks, and orchestrator status
"""
import os
import json
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, HTTPException

router = APIRouter()

# Task queue path from environment
TASK_QUEUE_PATH = Path(os.getenv("TASK_QUEUE_PATH",
                                  os.path.expanduser("~/projects/ai-orchestrator/task_queue")))


def _read_task_file(filepath: Path) -> Optional[dict]:
    """Read and parse a task JSON file"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def _list_tasks_in_dir(directory: Path) -> List[dict]:
    """List all task files in a directory"""
    if not directory.exists():
        return []

    tasks = []
    for task_file in directory.glob("*.json"):
        task_data = _read_task_file(task_file)
        if task_data:
            tasks.append(task_data)

    return tasks


@router.get("/stats")
async def get_stats():
    """Get orchestrator statistics"""
    stats = {
        "queued": len(list((TASK_QUEUE_PATH / "queued").glob("*.json"))) if (TASK_QUEUE_PATH / "queued").exists() else 0,
        "assigned": len(list((TASK_QUEUE_PATH / "assigned").glob("*.json"))) if (TASK_QUEUE_PATH / "assigned").exists() else 0,
        "in_progress": len(list((TASK_QUEUE_PATH / "in_progress").glob("*.json"))) if (TASK_QUEUE_PATH / "in_progress").exists() else 0,
        "completed": len(list((TASK_QUEUE_PATH / "completed").glob("*.json"))) if (TASK_QUEUE_PATH / "completed").exists() else 0,
        "failed": len(list((TASK_QUEUE_PATH / "failed").glob("*.json"))) if (TASK_QUEUE_PATH / "failed").exists() else 0,
    }

    stats["total"] = sum(stats.values())
    stats["active_workers"] = stats["in_progress"]

    return stats


@router.get("/workers")
async def get_workers():
    """Get list of active workers"""
    workers = []

    # Get tasks in progress (= active workers)
    in_progress_tasks = _list_tasks_in_dir(TASK_QUEUE_PATH / "in_progress")

    for task in in_progress_tasks:
        worker = {
            "worker_id": task.get("assigned_to", "unknown"),
            "task_id": task.get("task_id"),
            "task_title": task.get("task_title"),
            "started_at": task.get("started_at"),
            "worker_pid": task.get("worker_pid"),
            "cli_preference": task.get("cli_preference", "claude"),
        }
        workers.append(worker)

    return workers


@router.get("/tasks")
async def get_tasks(status: Optional[str] = None):
    """Get tasks by status"""
    if status:
        # Get tasks from specific status directory
        tasks = _list_tasks_in_dir(TASK_QUEUE_PATH / status)
        return {"status": status, "count": len(tasks), "tasks": tasks}

    # Get all tasks from all directories
    all_tasks = {
        "queued": _list_tasks_in_dir(TASK_QUEUE_PATH / "queued"),
        "assigned": _list_tasks_in_dir(TASK_QUEUE_PATH / "assigned"),
        "in_progress": _list_tasks_in_dir(TASK_QUEUE_PATH / "in_progress"),
        "completed": _list_tasks_in_dir(TASK_QUEUE_PATH / "completed"),
        "failed": _list_tasks_in_dir(TASK_QUEUE_PATH / "failed"),
    }

    return all_tasks


@router.get("/logs/{task_id}")
async def get_task_logs(task_id: str):
    """Get logs for a specific task"""
    results_dir = TASK_QUEUE_PATH / "results" / task_id

    if not results_dir.exists():
        raise HTTPException(status_code=404, detail="Task results not found")

    logs = {}

    # Read stdout
    stdout_file = results_dir / "stdout.log"
    if stdout_file.exists():
        logs["stdout"] = stdout_file.read_text()

    # Read stderr
    stderr_file = results_dir / "stderr.log"
    if stderr_file.exists():
        logs["stderr"] = stderr_file.read_text()

    # Read output summary
    output_file = results_dir / "output.txt"
    if output_file.exists():
        logs["output"] = output_file.read_text()

    return logs


@router.post("/cancel/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running task"""
    # TODO: Implement task cancellation
    # - Find task in in_progress/
    # - Kill worker process
    # - Move to failed/ with cancellation reason
    raise HTTPException(status_code=501, detail="Task cancellation not yet implemented")
