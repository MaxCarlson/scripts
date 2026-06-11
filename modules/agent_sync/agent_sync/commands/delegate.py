"""Delegate/review/verify command implementation."""

from pathlib import Path
import time

from agent_sync.adapters.factory import create_adapter
from agent_sync.config import load_config
from agent_sync.errors import PolicyError
from agent_sync.paths import config_path
from agent_sync.policy.delegation import enforce_external_policy, select_worker
from agent_sync.prompting.packs import build_delegation_prompt
from agent_sync.state.audit import AuditRecord, new_audit_id, utc_now, write_audit_artifacts
from agent_sync.tasks import DelegationTask


def read_prompt(*, prompt: str | None, file_path: Path | None) -> tuple[str, Path | None]:
    """Resolve prompt text from inline prompt or file."""
    if file_path is not None:
        return file_path.read_text(encoding="utf-8"), file_path
    if prompt is not None:
        return prompt, None
    raise ValueError("Provide -p/--prompt or -f/--file.")


def cmd_delegate(
    *,
    repo_root: Path,
    task_type: str,
    worker_name: str,
    context_level: str,
    prompt: str | None,
    file_path: Path | None,
    title: str | None,
    allow_external: bool,
    high_stakes: bool,
    readonly: bool,
    dry_run: bool,
    output_path: Path | None,
    output_json: bool,
) -> int:
    """Run a delegated worker task."""
    prompt_text, source_path = read_prompt(prompt=prompt, file_path=file_path)
    task = DelegationTask(
        task_type=task_type,
        prompt=prompt_text,
        repo_root=repo_root,
        context_level=context_level,
        title=title,
        source_path=source_path,
        high_stakes=high_stakes,
        readonly=readonly,
    )
    config = load_config(config_path(repo_root))
    worker = select_worker(config, task, preferred=worker_name)
    rendered_prompt = build_delegation_prompt(task)

    if dry_run or not allow_external:
        print(f"Planned worker: {worker.name}")
        print(f"Task type:      {task.task_type}")
        print(f"Context level:  {task.context_level}")
        print("\n--- PROMPT START ---\n")
        print(rendered_prompt)
        print("\n--- PROMPT END ---")
        if not allow_external:
            try:
                enforce_external_policy(allow_external=allow_external, worker=worker)
            except PolicyError as error:
                print(f"\nPolicy: {error}")
        return 0

    enforce_external_policy(allow_external=allow_external, worker=worker)
    adapter = create_adapter(repo_root, worker)
    audit_id = new_audit_id()
    start = time.monotonic()
    result = adapter.run(rendered_prompt, task_type=task_type, context_level=context_level)
    duration = time.monotonic() - start
    record = AuditRecord(
        audit_id=audit_id,
        created_at=utc_now(),
        worker=worker.name,
        task_type=task_type,
        context_level=context_level,
        high_stakes=high_stakes,
        repo_root=str(repo_root),
        prompt_path=str(repo_root / ".agent_sync" / "audit" / audit_id / "prompt.md"),
        output_path=str(repo_root / ".agent_sync" / "audit" / audit_id / "output.md"),
        status=result.status,
        exit_code=result.exit_code,
        duration_seconds=duration,
        error=result.error,
    )
    write_audit_artifacts(repo_root=repo_root, audit_id=audit_id, prompt=rendered_prompt, output=result.output, record=record)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.output, encoding="utf-8")
    if output_json:
        import json
        print(json.dumps(record.to_dict(), indent=2))
    else:
        print(result.output)
        print(f"\n[agent-sync] audit_id={audit_id} status={result.status} worker={worker.name}")
    return 0 if result.status == "ok" else 1
