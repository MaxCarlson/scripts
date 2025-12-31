"""
Results API Router
Endpoints for accessing task execution results and artifacts
"""
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

# Task queue path
TASK_QUEUE_PATH = Path(os.getenv("TASK_QUEUE_PATH",
                                  os.path.expanduser("~/projects/ai-orchestrator/task_queue")))


@router.get("/{task_id}")
async def get_results(task_id: str):
    """Get task execution results"""
    results_dir = TASK_QUEUE_PATH / "results" / task_id

    if not results_dir.exists():
        raise HTTPException(status_code=404, detail="Task results not found")

    results = {
        "task_id": task_id,
        "results_path": str(results_dir),
    }

    # Read output summary
    output_file = results_dir / "output.txt"
    if output_file.exists():
        results["summary"] = output_file.read_text()

    # List modified files
    files_modified_file = results_dir / "files_modified.txt"
    if files_modified_file.exists():
        results["files_modified"] = files_modified_file.read_text().splitlines()

    # Check for artifacts
    artifacts_dir = results_dir / "artifacts"
    if artifacts_dir.exists():
        artifacts = []
        for artifact_file in artifacts_dir.rglob("*"):
            if artifact_file.is_file():
                rel_path = artifact_file.relative_to(artifacts_dir)
                artifacts.append(str(rel_path))
        results["artifacts"] = artifacts

    return results


@router.get("/{task_id}/logs")
async def get_logs(task_id: str):
    """Get task logs (stdout/stderr)"""
    results_dir = TASK_QUEUE_PATH / "results" / task_id

    if not results_dir.exists():
        raise HTTPException(status_code=404, detail="Task results not found")

    logs = {}

    stdout_file = results_dir / "stdout.log"
    if stdout_file.exists():
        logs["stdout"] = stdout_file.read_text()

    stderr_file = results_dir / "stderr.log"
    if stderr_file.exists():
        logs["stderr"] = stderr_file.read_text()

    return logs


@router.get("/{task_id}/artifacts")
async def list_artifacts(task_id: str):
    """List all artifacts for a task"""
    artifacts_dir = TASK_QUEUE_PATH / "results" / task_id / "artifacts"

    if not artifacts_dir.exists():
        return []

    artifacts = []
    for artifact_file in artifacts_dir.rglob("*"):
        if artifact_file.is_file():
            rel_path = artifact_file.relative_to(artifacts_dir)
            artifacts.append({
                "path": str(rel_path),
                "size": artifact_file.stat().st_size,
                "modified": artifact_file.stat().st_mtime,
            })

    return artifacts


@router.get("/{task_id}/artifacts/{artifact_path:path}")
async def download_artifact(task_id: str, artifact_path: str):
    """Download a specific artifact"""
    artifact_file = TASK_QUEUE_PATH / "results" / task_id / "artifacts" / artifact_path

    if not artifact_file.exists() or not artifact_file.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Security check: ensure file is within artifacts directory
    try:
        artifact_file.relative_to(TASK_QUEUE_PATH / "results" / task_id / "artifacts")
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=artifact_file,
        filename=artifact_file.name,
        media_type="application/octet-stream"
    )
