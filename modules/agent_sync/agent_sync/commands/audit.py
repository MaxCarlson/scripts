"""Audit CLI commands."""

from pathlib import Path

from agent_sync.state.audit import list_audit_records, load_audit_record


def cmd_audit_list(repo_root: Path, *, limit: int) -> int:
    """List audit records."""
    records = list_audit_records(repo_root)[:limit]
    print(f"{'AUDIT ID':24s} {'WORKER':16s} {'TYPE':10s} {'STATUS':8s} CREATED")
    print(f"{'-' * 24} {'-' * 16} {'-' * 10} {'-' * 8} {'-' * 25}")
    for record in records:
        print(f"{record.audit_id:24s} {record.worker:16s} {record.task_type:10s} {record.status:8s} {record.created_at}")
    return 0


def cmd_audit_show(repo_root: Path, *, audit_id: str, show_prompt: bool) -> int:
    """Show a single audit record."""
    record, prompt, output = load_audit_record(repo_root, audit_id)
    print(f"# Audit {record.audit_id}\n")
    print(f"- worker: {record.worker}")
    print(f"- task_type: {record.task_type}")
    print(f"- status: {record.status}")
    print(f"- created_at: {record.created_at}")
    print(f"- duration_seconds: {record.duration_seconds:.2f}")
    if record.error:
        print(f"- error: {record.error}")
    if show_prompt:
        print("\n## Prompt\n")
        print(prompt)
    print("\n## Output\n")
    print(output)
    return 0
