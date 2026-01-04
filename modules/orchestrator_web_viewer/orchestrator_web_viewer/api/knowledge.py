"""
Knowledge Manager API Router
Endpoints for projects and tasks from PostgreSQL
"""
import os
import uuid
from typing import Dict, List, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from orchestrator_web_viewer.integrations.orchestrator_client import orchestrator_post

router = APIRouter()

# PostgreSQL connection config
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "km_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "knowledge_manager")


async def get_db_connection():
    """Get database connection"""
    return await asyncpg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        database=POSTGRES_DB
    )


@router.get("/projects")
async def get_projects():
    """Get all projects"""
    conn = await get_db_connection()
    try:
        rows = await conn.fetch("""
            SELECT id, name, status, created_at, modified_at
            FROM projects
            ORDER BY name
        """)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)
    status: str = Field(default="active")
    track: bool = True
    repo_path: Optional[str] = None


class TaskBase(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    status: Optional[str] = Field(default=None)
    priority: Optional[int] = Field(default=None, ge=1, le=10)
    project_id: Optional[str] = None
    parent_task_id: Optional[str] = None


class TaskCreate(TaskBase):
    title: str = Field(..., min_length=1)
    priority: Optional[int] = Field(default=5, ge=1, le=10)


class TaskUpdate(TaskBase):
    """Partial updates for an existing task."""
    pass


def normalize_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {value}") from exc


def normalize_task_row(row: asyncpg.Record) -> Dict:
    data = dict(row)
    for key in ("id", "project_id", "parent_task_id"):
        if data.get(key):
            data[key] = str(data[key])
    return data


@router.post("/projects")
async def create_project(payload: ProjectCreate):
    """Create a new project and optionally enable memory tracking."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")

    if payload.track and not payload.repo_path:
        raise HTTPException(status_code=400, detail="Repository path required when tracking is enabled")

    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO projects (name, status)
            VALUES ($1, $2)
            RETURNING id, name, status, created_at, modified_at
            """,
            name,
            payload.status,
        )
    finally:
        await conn.close()

    project = dict(row)
    project_id = str(project["id"])

    if payload.track and payload.repo_path:
        repo_path = payload.repo_path.strip()
        if not repo_path:
            raise HTTPException(status_code=400, detail="Repository path cannot be empty when tracking")
        await orchestrator_post(
            f"/projects/{project_id}/tracking",
            {
                "is_tracked": True,
                "repo_path": repo_path,
                "repo_paths": [repo_path],
            },
        )
    elif payload.repo_path:
        # Store repo path for reference but leave tracking disabled
        await orchestrator_post(
            f"/projects/{project_id}/tracking",
            {
                "is_tracked": False,
                "repo_path": payload.repo_path.strip(),
                "repo_paths": [payload.repo_path.strip()],
            },
        )

    project["id"] = project_id
    return project


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get a specific project"""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow("""
            SELECT id, name, status, created_at, modified_at
            FROM projects
            WHERE id = $1
        """, project_id)

        if not row:
            raise HTTPException(status_code=404, detail="Project not found")

        return dict(row)
    finally:
        await conn.close()


@router.get("/tasks")
async def get_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
):
    """Get tasks with optional filters"""
    conn = await get_db_connection()
    try:
        query = """
            SELECT id, title, status, priority, due_date, project_id,
                   created_at, modified_at
            FROM tasks
            WHERE 1=1
        """
        params = []

        if project_id:
            params.append(project_id)
            query += f" AND project_id = ${len(params)}"

        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]
    finally:
        await conn.close()


@router.post("/tasks")
async def create_task(payload: TaskCreate):
    """Create a new task."""
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Task title is required")

    project_uuid = normalize_uuid(payload.project_id) if payload.project_id else None
    parent_uuid = normalize_uuid(payload.parent_task_id) if payload.parent_task_id else None
    priority = payload.priority or 5
    status_value = (payload.status or "todo").strip().lower()

    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO tasks (title, status, priority, project_id, parent_task_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, title, status, priority, project_id, parent_task_id,
                      created_at, modified_at
            """,
            title,
            status_value,
            priority,
            project_uuid,
            parent_uuid,
        )
    finally:
        await conn.close()

    return normalize_task_row(row)


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate):
    """Update task metadata."""
    updates = []
    values = []

    if payload.title is not None:
        new_title = payload.title.strip()
        if not new_title:
            raise HTTPException(status_code=400, detail="Task title cannot be empty")
        updates.append(f"title = ${len(values) + 1}")
        values.append(new_title)

    if payload.status is not None:
        updates.append(f"status = ${len(values) + 1}")
        values.append(payload.status.strip().lower())

    if payload.priority is not None:
        updates.append(f"priority = ${len(values) + 1}")
        values.append(payload.priority)

    if payload.project_id is not None:
        updates.append(f"project_id = ${len(values) + 1}")
        values.append(normalize_uuid(payload.project_id))

    if payload.parent_task_id is not None:
        updates.append(f"parent_task_id = ${len(values) + 1}")
        parent_uuid = normalize_uuid(payload.parent_task_id)
        values.append(parent_uuid)

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    task_uuid = normalize_uuid(task_id)
    values.append(task_uuid)

    query = f"""
        UPDATE tasks
        SET {', '.join(updates)}, modified_at = timezone('utc', now())
        WHERE id = ${len(values)}
        RETURNING id, title, status, priority, project_id, parent_task_id,
                  created_at, modified_at
    """

    conn = await get_db_connection()
    try:
        row = await conn.fetchrow(query, *values)
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
    finally:
        await conn.close()

    return normalize_task_row(row)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    """Delete a task (and potentially its subtasks via DB constraints)."""
    task_uuid = normalize_uuid(task_id)
    conn = await get_db_connection()
    try:
        result = await conn.execute("DELETE FROM tasks WHERE id = $1", task_uuid)
    finally:
        await conn.close()

    deleted = result.split()[-1]
    if deleted == "0":
        raise HTTPException(status_code=404, detail="Task not found")
    return Response(status_code=204)


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a specific task"""
    conn = await get_db_connection()
    try:
        row = await conn.fetchrow("""
            SELECT id, title, status, priority, due_date, project_id,
                   created_at, modified_at
            FROM tasks
            WHERE id = $1
        """, task_id)

        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        return dict(row)
    finally:
        await conn.close()


@router.post("/tasks/{task_id}/assign")
async def assign_task_to_ai(task_id: str):
    """Assign a task to the AI queue"""
    # TODO: Implement task assignment
    # - Get task from PostgreSQL
    # - Create task in queue using TaskQueue
    # - Return queue task ID
    raise HTTPException(status_code=501, detail="Task assignment not yet implemented")
@router.delete("/projects/{project_id}", status_code=204)
async def delete_project_route(project_id: str):
    """Delete a project and its tasks."""
    project_uuid = normalize_uuid(project_id)
    conn = await get_db_connection()
    try:
        await conn.execute("DELETE FROM tasks WHERE project_id = $1", project_uuid)
        result = await conn.execute("DELETE FROM projects WHERE id = $1", project_uuid)
    finally:
        await conn.close()

    deleted = result.split()[-1]
    if deleted == "0":
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=204)
