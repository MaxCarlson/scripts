"""
Knowledge Manager API Router
Endpoints for projects and tasks from PostgreSQL
"""
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException
import asyncpg
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
            },
        )
    elif payload.repo_path:
        # Store repo path for reference but leave tracking disabled
        await orchestrator_post(
            f"/projects/{project_id}/tracking",
            {
                "is_tracked": False,
                "repo_path": payload.repo_path.strip(),
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
