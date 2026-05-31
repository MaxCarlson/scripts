"""Render agent_sync Markdown documents from DB state."""
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .templates import AGENT_CONTRACT, HANDOFF, SESSION_BRIEF


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def render_session_brief(
    conn: sqlite3.Connection,
    task_id: str,
    run_id: str,
) -> str:
    """Render SESSION_BRIEF.md content for the given task and run."""
    task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not task or not run:
        raise ValueError(f"task_id={task_id} or run_id={run_id} not found")

    active_claims = conn.execute(
        "SELECT path, access_mode FROM claims WHERE run_id=? AND released_at IS NULL",
        (run_id,),
    ).fetchall()
    if active_claims:
        claims_section = "\n".join(
            f"- `{r['path']}` ({r['access_mode']})" for r in active_claims
        )
    else:
        claims_section = "_No file claims active yet._"

    last_handoff = conn.execute(
        """
        SELECT handoff_md_path FROM handoffs
        WHERE task_id=? AND status IN ('proposed','accepted')
        ORDER BY created_at DESC LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    handoff_context = (
        f"See `{last_handoff['handoff_md_path']}`" if last_handoff
        else "_No prior handoff. This is the first run._"
    )

    return SESSION_BRIEF.format(
        task_id=task_id,
        run_id=run_id,
        agent_name=run["agent_name"],
        branch_name=run["branch_name"],
        worktree_path=run["worktree_path"],
        generated_at=_now(),
        summary_md=task["summary_md"],
        task_status=task["status"],
        mode=run["mode"],
        claims_section=claims_section,
        acceptance_md=task["acceptance_md"] or "_None specified._",
        handoff_context=handoff_context,
    )


def render_handoff(
    conn: sqlite3.Connection,
    task_id: str,
    from_run_id: str,
    to_agent: str,
    *,
    changed_files: Optional[list[str]] = None,
    validation_output: Optional[str] = None,
    blocking_issues: Optional[list[str]] = None,
    open_questions: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
    integration_notes: Optional[str] = None,
) -> str:
    """Render HANDOFF.md content for a stop/handoff event."""
    task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (from_run_id,)).fetchone()
    if not task or not run:
        raise ValueError("task_id or run_id not found")

    changed_section = (
        "\n".join(f"- `{f}`" for f in changed_files)
        if changed_files else "_No file changes recorded._"
    )
    validation_section = validation_output or "_Validation not run or not recorded._"
    blocking_section = (
        "\n".join(f"- {i}" for i in blocking_issues)
        if blocking_issues else "_None._"
    )
    questions_section = (
        "\n".join(f"- {q}" for q in open_questions)
        if open_questions else "_None._"
    )
    steps_section = (
        "\n".join(f"- {s}" for s in next_steps)
        if next_steps else "_None specified._"
    )

    return HANDOFF.format(
        task_id=task_id,
        from_run_id=from_run_id,
        from_agent=run["agent_name"],
        to_agent=to_agent,
        created_at=_now(),
        target_branch=task["target_branch"],
        work_branch=run["branch_name"],
        worktree_path=run["worktree_path"],
        summary_md=task["summary_md"],
        changed_files_section=changed_section,
        validation_section=validation_section,
        blocking_issues=blocking_section,
        open_questions=questions_section,
        next_steps=steps_section,
        integration_notes=integration_notes or "_None._",
    )


def render_agent_contract() -> str:
    """Return the static AGENT_CONTRACT.md content."""
    return AGENT_CONTRACT
