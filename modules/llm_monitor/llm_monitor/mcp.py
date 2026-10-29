"""Read-only correlation against an explicitly supplied MCP job snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SAFE_FIELDS = (
    "jobId", "sessionId", "messageId", "directory", "agent", "model",
    "status", "startedAt", "updatedAt", "completedAt",
)


def load_job_snapshot(path: str | Path) -> dict[str, Any]:
    """Read a user-selected JSON snapshot; never contacts MCP or mutates job state."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}", "jobs": []}
    rows = raw.get("jobs") if isinstance(raw, dict) else None
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return {"available": False, "error": "snapshot must contain a jobs array or object", "jobs": []}
    jobs = [{key: value.get(key) for key in _SAFE_FIELDS if key in value}
            for value in rows if isinstance(value, dict)]
    return {"available": True, "jobs": jobs}


def correlate_job(
    session_id: str,
    session_directory: str | None,
    snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer explicit session IDs; directory-only matches remain qualified hypotheses."""
    if not snapshot or not snapshot.get("available"):
        return {"status": "unavailable", "job": None, "classification": "unknown",
                "evidence": [], "error": snapshot.get("error") if snapshot else None}
    jobs = [job for job in snapshot.get("jobs", []) if isinstance(job, dict)]
    explicit = [job for job in jobs if job.get("sessionId") == session_id]
    if len(explicit) == 1:
        job = explicit[0]
        return {"status": "correlated", "job": job, "classification": "observed",
                "evidence": [{"kind": "explicit_session_id", "session_id": session_id}]}
    if len(explicit) > 1:
        return {"status": "ambiguous", "job": None, "classification": "observed",
                "evidence": [{"kind": "multiple_explicit_matches", "job_ids": [j.get("jobId") for j in explicit]}]}
    directory_matches = [job for job in jobs if session_directory and job.get("directory") == session_directory]
    if len(directory_matches) == 1:
        return {"status": "probable_directory_match", "job": directory_matches[0],
                "classification": "hypothesis",
                "evidence": [{"kind": "directory_and_session_context", "directory": session_directory,
                              "session_id": session_id}],
                "warning": "Directory match does not establish job ownership."}
    if len(directory_matches) > 1:
        return {"status": "ambiguous", "job": None, "classification": "hypothesis",
                "evidence": [{"kind": "multiple_directory_matches", "directory": session_directory,
                              "job_ids": [j.get("jobId") for j in directory_matches]}]}
    return {"status": "unresolved", "job": None, "classification": "observed",
            "evidence": [{"kind": "no_session_id_match", "session_id": session_id,
                          "directory_checked": bool(session_directory)}],
            "warning": "A missing MCP mapping does not establish worker failure."}
